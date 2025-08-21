pipeline {
    agent any

    environment {
        DEPLOY_DIR   = '/opt/influencer-agent'
        BRANCH       = 'production'
        SERVICE_NAME = 'influencer-agent'
        REMOTE_USER  = 'ubuntu'
        REMOTE_HOST  = '13.218.245.191'
    }

    stages {
        stage('SonarQube Analysis') {
            steps {
                // Inject SONARQUBE_TOKEN from Jenkins credentials (Secret Text)
                withCredentials([string(credentialsId: 'SONARQUBE_TOKEN', variable: 'SONARQUBE_TOKEN')]) {
                    withSonarQubeEnv('sonarqube') { // SonarQube server name from Manage Jenkins
                        script {
                            // Reference the SonarQube Scanner tool configured in Jenkins
                            def scannerHome = tool 'sonarqube scanner'
                            sh """
                                ${scannerHome}/bin/sonar-scanner \
                                  -Dsonar.projectKey=influencer-agent \
                                  -Dsonar.sources=. \
                                  -Dsonar.host.url=https://sonarqube.techthree.io \
                                  -Dsonar.token=${SONARQUBE_TOKEN} \
                                  -Dsonar.qualitygate.wait=true
                            """
                        }
                    }
                }
            }
        }

        stage('Quality Gate') {
            steps {
                timeout(time: 5, unit: 'MINUTES') {
                    waitForQualityGate abortPipeline: true
                }
            }
        }

        stage('Deploy') {
            steps {
                sshagent(['Genealpha-Frontend-credentials']) {
                    sh """
                        ssh -o StrictHostKeyChecking=no ${REMOTE_USER}@${REMOTE_HOST} '
                            echo "Connected to server"

                            # Pull latest code from the production branch
                            cd ${DEPLOY_DIR}
                            git checkout ${BRANCH}
                            git pull origin ${BRANCH}

                            # Stop and remove the specific container
                            sudo docker-compose stop ${SERVICE_NAME}
                            sudo docker-compose rm -f ${SERVICE_NAME}

                            # Rebuild and start the specific container
                            sudo docker-compose up --build -d ${SERVICE_NAME}
                        '
                    """
                }
            }
        }
    }
}

